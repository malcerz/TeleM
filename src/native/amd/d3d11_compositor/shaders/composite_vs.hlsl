struct VS_OUTPUT {
    float4 Pos : SV_POSITION;
    float2 Tex : TEXCOORD0;
};

VS_OUTPUT main(uint id : SV_VertexID) {
    VS_OUTPUT output;
    output.Tex = float2((id == 2) ? 2.0 : 0.0, (id == 1) ? 2.0 : 0.0);
    output.Pos = float4(output.Tex * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    return output;
}
