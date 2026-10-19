#ifndef ICON_CACHE_H
#define ICON_CACHE_H

#include <d2d1_1.h>
#include <wincodec.h>
#include <string>
#include <map>

class IconCache {
public:
    IconCache();
    ~IconCache();

    bool Init();
    void Clear();

    ID2D1Bitmap* GetIcon(ID2D1DeviceContext* pD2D, const std::string& icon_name);

private:
    IWICImagingFactory* m_pWicFactory;
    std::map<std::string, ID2D1Bitmap*> m_bitmaps;
    std::wstring m_base_dir;
};

#endif // ICON_CACHE_H
