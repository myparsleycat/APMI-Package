// AP bone matrices contain four float4 columns.
ByteAddressBuffer Rest : register(t0);
ByteAddressBuffer Blend : register(t1);
struct Bone { float4 c0; float4 c1; float4 c2; float4 c3; };
StructuredBuffer<Bone> Bones : register(t2);
RWByteAddressBuffer Posed : register(u0);

[numthreads(64, 1, 1)]
void main(uint3 thread : SV_DispatchThreadID)
{
    uint vertex = thread.x;
    uint positionBytes;
    Rest.GetDimensions(positionBytes);
    if (vertex >= positionBytes / 40) return;
    uint boneCount, boneStride;
    Bones.GetDimensions(boneCount, boneStride);
    uint offset = vertex * 40;
    float3 position = asfloat(Rest.Load3(offset));
    float3 normal = asfloat(Rest.Load3(offset + 12));
    float4 tangent = asfloat(Rest.Load4(offset + 24));
    float4 weights = asfloat(Blend.Load4(vertex * 32));
    uint4 indices = Blend.Load4(vertex * 32 + 16);
    float3 c0 = 0, c1 = 0, c2 = 0, c3 = 0;
    [unroll] for (uint i = 0; i < 4; ++i) {
        if (weights[i] != 0 && indices[i] < boneCount) {
            Bone bone = Bones[indices[i]];
            c0 += bone.c0.xyz * weights[i];
            c1 += bone.c1.xyz * weights[i];
            c2 += bone.c2.xyz * weights[i];
            c3 += bone.c3.xyz * weights[i];
        }
    }
    Posed.Store3(offset, asuint(c0 * position.x + c1 * position.y + c2 * position.z + c3));
    Posed.Store3(offset + 12, asuint(c0 * normal.x + c1 * normal.y + c2 * normal.z));
    Posed.Store4(offset + 24, asuint(float4(c0 * tangent.x + c1 * tangent.y + c2 * tangent.z, tangent.w)));
}
