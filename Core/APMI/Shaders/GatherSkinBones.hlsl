struct Bone { float4 c0; float4 c1; float4 c2; float4 c3; };
StructuredBuffer<Bone> NativeBones : register(t0);
StructuredBuffer<uint2> BoneMap : register(t1);
RWStructuredBuffer<Bone> MergedBones : register(u0);

[numthreads(64, 1, 1)]
void main(uint3 thread : SV_DispatchThreadID)
{
    uint mapCount, stride;
    BoneMap.GetDimensions(mapCount, stride);
    if (thread.x >= mapCount) return;
    uint2 slots = BoneMap[thread.x];
    uint sourceCount, destinationCount;
    NativeBones.GetDimensions(sourceCount, stride);
    MergedBones.GetDimensions(destinationCount, stride);
    if (slots.x < sourceCount && slots.y < destinationCount)
        MergedBones[slots.y] = NativeBones[slots.x];
}
