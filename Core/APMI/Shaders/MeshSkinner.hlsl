// AP bone matrices contain four float4 columns.
// Blend is 32 bytes per vertex (float4 weights, uint4 indices) or
// 64 bytes per vertex (float weights[8], uint indices[8]).
ByteAddressBuffer Rest : register(t0);
ByteAddressBuffer Blend : register(t1);
struct Bone { float4 c0; float4 c1; float4 c2; float4 c3; };
StructuredBuffer<Bone> Bones : register(t2);
RWByteAddressBuffer Posed : register(u0);

void accumulate(float weight, uint index, uint boneCount, inout float3 c0, inout float3 c1, inout float3 c2, inout float3 c3)
{
    if (weight != 0 && index < boneCount) {
        Bone bone = Bones[index];
        c0 += bone.c0.xyz * weight;
        c1 += bone.c1.xyz * weight;
        c2 += bone.c2.xyz * weight;
        c3 += bone.c3.xyz * weight;
    }
}

[numthreads(64, 1, 1)]
void main(uint3 thread : SV_DispatchThreadID)
{
    uint vertex = thread.x;
    uint positionBytes, blendBytes;
    Rest.GetDimensions(positionBytes);
    uint vertexCount = positionBytes / 40;
    if (vertex >= vertexCount) return;
    Blend.GetDimensions(blendBytes);
    uint boneCount, boneStride;
    Bones.GetDimensions(boneCount, boneStride);
    uint offset = vertex * 40;
    float3 position = asfloat(Rest.Load3(offset));
    float3 normal = asfloat(Rest.Load3(offset + 12));
    float4 tangent = asfloat(Rest.Load4(offset + 24));
    float3 c0 = 0, c1 = 0, c2 = 0, c3 = 0;
    if (blendBytes / vertexCount == 64) {
        uint blend = vertex * 64;
        float4 weights[2] = { asfloat(Blend.Load4(blend)), asfloat(Blend.Load4(blend + 16)) };
        uint4 indices[2] = { Blend.Load4(blend + 32), Blend.Load4(blend + 48) };
        [unroll] for (uint i = 0; i < 8; ++i)
            accumulate(weights[i / 4][i % 4], indices[i / 4][i % 4], boneCount, c0, c1, c2, c3);
    } else {
        float4 weights = asfloat(Blend.Load4(vertex * 32));
        uint4 indices = Blend.Load4(vertex * 32 + 16);
        [unroll] for (uint i = 0; i < 4; ++i)
            accumulate(weights[i], indices[i], boneCount, c0, c1, c2, c3);
    }
    Posed.Store3(offset, asuint(c0 * position.x + c1 * position.y + c2 * position.z + c3));
    Posed.Store3(offset + 12, asuint(c0 * normal.x + c1 * normal.y + c2 * normal.z));
    Posed.Store4(offset + 24, asuint(float4(c0 * tangent.x + c1 * tangent.y + c2 * tangent.z, tangent.w)));
}
