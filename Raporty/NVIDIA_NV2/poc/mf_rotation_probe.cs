// Probe Windows Media Foundation rotation attribute for a video file.
// Build & run: Add-Type in PowerShell (see run_mf_rotation_probe.ps1)
using System;
using System.Runtime.InteropServices;

public static class MfRotationProbe
{
    // MF_MT_VIDEO_ROTATION = {C36A7176-FE76-4D6F-A83B-AB4E74D9A1E1}
    static readonly Guid MF_MT_VIDEO_ROTATION = new Guid(0xC36A7176, 0xFE76, 0x4D6F, 0xA8, 0x3B, 0xAB, 0x4E, 0x74, 0xD9, 0xA1, 0xE1);

    [DllImport("mfplat.dll")]
    static extern int MFStartup(int Version, int dwFlags);

    [DllImport("mfplat.dll")]
    static extern void MFShutdown();

    [DllImport("mfreadwrite.dll")]
    static extern int MFCreateSourceReaderFromURL(
        [MarshalAs(UnmanagedType.LPWStr)] string pwszURL,
        IntPtr pAttributes, out IntPtr ppReader);

    [DllImport("mfplat.dll")]
    static extern int MFCreateMediaType(out IntPtr ppMFType);

    // IMFSourceReader methods (vtable) - we use COM interop via interface below

    [ComImport, Guid("70AE66F2-C809-4E4F-8915-BDCB406B7993"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMFSourceReader
    {
        [PreserveSig] int GetStreamSelection(int dwStreamIndex, out bool pfSelected);
        [PreserveSig] int SetStreamSelection(int dwStreamIndex, bool fSelected);
        [PreserveSig] int GetNativeMediaType(int dwStreamIndex, int dwMediaTypeIndex, out IntPtr ppMediaType);
        [PreserveSig] int GetCurrentMediaType(int dwStreamIndex, out IntPtr ppMediaType);
        [PreserveSig] int SetCurrentMediaType(int dwStreamIndex, IntPtr pdwReserved, IntPtr pMediaType);
        [PreserveSig] int SetCurrentPosition(Guid guidTimeFormat, IntPtr varPosition);
        [PreserveSig] int ReadSample(int dwStreamIndex, int dwControlFlags, out int pdwActualStreamIndex,
            out int pdwStreamFlags, out long pllTimestamp, out IntPtr ppSample);
        [PreserveSig] int Flush(int dwStreamIndex);
        [PreserveSig] int GetServiceForStream(int dwStreamIndex, Guid guidService, Guid riid, out IntPtr ppObject);
        [PreserveSig] int GetPresentationAttribute(int dwStreamIndex, Guid guidAttribute, IntPtr pvarValue);
    }

    [ComImport, Guid("44AE0FA8-EA31-4109-8D2E-4CAE4997C555"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IMFAttributes
    {
        [PreserveSig] int GetItem(Guid guidKey, IntPtr pValue);
        [PreserveSig] int GetItemType(Guid guidKey, out int pType);
        [PreserveSig] int CompareItem(Guid guidKey, int valueType, IntPtr value, out bool pbResult);
        [PreserveSig] int Compare(IntPtr pTheirs, int MatchType, out bool pbResult);
        [PreserveSig] int GetUINT32(Guid guidKey, out uint punValue);
        [PreserveSig] int GetUINT64(Guid guidKey, out ulong punValue);
        [PreserveSig] int GetDouble(Guid guidKey, out double pfValue);
        [PreserveSig] int GetGUID(Guid guidKey, out Guid pguidValue);
        [PreserveSig] int GetStringLength(Guid guidKey, out int pcchLength);
        [PreserveSig] int GetString(Guid guidKey, IntPtr pwszValue, int cchBufSize, out int pcchLength);
        [PreserveSig] int GetAllocatedString(Guid guidKey, out IntPtr ppwszValue, out int pcchLength);
        [PreserveSig] int GetBlobSize(Guid guidKey, out int pcbBlobSize);
        [PreserveSig] int GetBlob(Guid guidKey, IntPtr pBuf, int cbBufSize, out int pcbBlobSize);
        [PreserveSig] int GetAllocatedBlob(Guid guidKey, out IntPtr ppBuf, out int pcbSize);
        [PreserveSig] int GetUnknown(Guid guidKey, ref Guid riid, out IntPtr ppunk);
        [PreserveSig] int SetItem(Guid guidKey, int valueType, IntPtr value);
        [PreserveSig] int DeleteItem(Guid guidKey);
        [PreserveSig] int DeleteAllItems();
        [PreserveSig] int SetUINT32(Guid guidKey, uint unValue);
        [PreserveSig] int SetUINT64(Guid guidKey, ulong unValue);
        [PreserveSig] int SetDouble(Guid guidKey, double fValue);
        [PreserveSig] int SetGUID(Guid guidKey, Guid guidValue);
        [PreserveSig] int SetString(Guid guidKey, [MarshalAs(UnmanagedType.LPWStr)] string wszValue);
        [PreserveSig] int SetBlob(Guid guidKey, byte[] pBuf, int cbBufSize);
        [PreserveSig] int SetUnknown(Guid guidKey, IntPtr pUnknown);
        [PreserveSig] int LockStore();
        [PreserveSig] int UnlockStore();
        [PreserveSig] int GetCount(out int pcItems);
        [PreserveSig] int GetItemByIndex(int unIndex, out Guid pguidKey, IntPtr pValue);
        [PreserveSig] int CopyAllItems(IntPtr pDest);
    }

    public static int Run(string path)
    {
        int hr = MFStartup(0x00020070 /*MF_VERSION 2.70*/, 0);
        if (hr != 0) { Console.WriteLine("MFStartup failed hr=0x" + hr.ToString("X8")); return 1; }
        try
        {
            IntPtr readerPtr;
            hr = MFCreateSourceReaderFromURL(path, IntPtr.Zero, out readerPtr);
            if (hr != 0) { Console.WriteLine("MFCreateSourceReaderFromURL failed hr=0x" + hr.ToString("X8")); return 1; }
            var reader = (IMFSourceReader)Marshal.GetObjectForIUnknown(readerPtr);
            try
            {
                IntPtr mtPtr;
                hr = reader.GetCurrentMediaType(0, out mtPtr);
                if (hr != 0) { Console.WriteLine("GetCurrentMediaType failed hr=0x" + hr.ToString("X8")); return 1; }
                var attrs = (IMFAttributes)Marshal.GetObjectForIUnknown(mtPtr);
                uint rot;
                hr = attrs.GetUINT32(MF_MT_VIDEO_ROTATION, out rot);
                if (hr == 0)
                    Console.WriteLine("MF_MT_VIDEO_ROTATION = " + rot);
                else
                    Console.WriteLine("MF_MT_VIDEO_ROTATION absent hr=0x" + hr.ToString("X8"));
                return 0;
            }
            finally { Marshal.Release(readerPtr); }
        }
        finally { MFShutdown(); }
    }
}
