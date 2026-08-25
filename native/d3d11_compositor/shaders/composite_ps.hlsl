Texture2D baseTexture : register(t0);
Texture2D hudTexture : register(t1);
SamplerState samLinear : register(s0);

struct PS_INPUT {
    float4 Pos : SV_POSITION;
    float2 Tex : TEXCOORD0;
};

float4 main(PS_INPUT input) : SV_Target {
    float4 baseColor = baseTexture.Sample(samLinear, input.Tex);
    float4 hudColor  = hudTexture.Sample(samLinear, input.Tex);

    // Straight Alpha Blending
    // Out_RGB = HUD_RGB * HUD_Alpha + Base_RGB * (1.0 - HUD_Alpha)
    // Out_Alpha = HUD_Alpha + Base_Alpha * (1.0 - HUD_Alpha)
    float3 blendedRGB = hudColor.rgb * hudColor.a + baseColor.rgb * (1.0 - hudColor.a);
    float blendedA = hudColor.a + baseColor.a * (1.0 - hudColor.a);

    return float4(blendedRGB, blendedA);
}
