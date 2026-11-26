#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using Microsoft::WRL::ComPtr;

static void check(HRESULT hr) {
    if (FAILED(hr)) throw std::runtime_error("D3D11 error " + std::to_string(static_cast<unsigned>(hr)));
}
static std::vector<char> read(const wchar_t* path) {
    std::ifstream file(std::filesystem::path(path), std::ios::binary);
    if (!file) throw std::runtime_error("Cannot read input");
    return {std::istreambuf_iterator<char>(file), {}};
}

static void gather(int argc, wchar_t** argv) {
    if (argc < 7 || (argc - 5) % 2)
        throw std::runtime_error("skin_gpu --gather shader bone-count output bones map [bones map...]");
    const auto count = static_cast<UINT>(std::stoul(argv[3]));
    if (!count || count > 4096) throw std::runtime_error("Invalid gathered bone count");
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    check(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, nullptr, 0,
                           D3D11_SDK_VERSION, &device, nullptr, &context));
    ComPtr<ID3DBlob> code, errors;
    const auto hr = D3DCompileFromFile(argv[2], nullptr, D3D_COMPILE_STANDARD_FILE_INCLUDE,
                                      "main", "cs_5_0", 0, 0, &code, &errors);
    if (errors) std::cerr.write(static_cast<char*>(errors->GetBufferPointer()), errors->GetBufferSize());
    check(hr);
    ComPtr<ID3D11ComputeShader> shader;
    check(device->CreateComputeShader(code->GetBufferPointer(), code->GetBufferSize(), nullptr, &shader));

    D3D11_BUFFER_DESC output_desc{};
    output_desc.ByteWidth = count * 64;
    output_desc.BindFlags = D3D11_BIND_UNORDERED_ACCESS;
    output_desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;
    output_desc.StructureByteStride = 64;
    ComPtr<ID3D11Buffer> output;
    check(device->CreateBuffer(&output_desc, nullptr, &output));
    ComPtr<ID3D11UnorderedAccessView> uav;
    check(device->CreateUnorderedAccessView(output.Get(), nullptr, &uav));
    ID3D11UnorderedAccessView* bound = uav.Get();
    context->CSSetShader(shader.Get(), nullptr, 0);
    context->CSSetUnorderedAccessViews(0, 1, &bound, nullptr);

    for (int argument = 5; argument < argc; argument += 2) {
        std::array<std::vector<char>, 2> data{read(argv[argument]), read(argv[argument + 1])};
        std::array<ComPtr<ID3D11ShaderResourceView>, 2> views;
        const std::array<UINT, 2> strides{64, 8};
        for (size_t index = 0; index < strides.size(); ++index) {
            if (data[index].empty() || data[index].size() % strides[index])
                throw std::runtime_error("Invalid gather input");
            D3D11_BUFFER_DESC desc{};
            desc.ByteWidth = static_cast<UINT>(data[index].size());
            desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
            desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_STRUCTURED;
            desc.StructureByteStride = strides[index];
            D3D11_SUBRESOURCE_DATA initial{data[index].data(), 0, 0};
            ComPtr<ID3D11Buffer> buffer;
            check(device->CreateBuffer(&desc, &initial, &buffer));
            check(device->CreateShaderResourceView(buffer.Get(), nullptr, &views[index]));
        }
        std::array<ID3D11ShaderResourceView*, 2> inputs{views[0].Get(), views[1].Get()};
        context->CSSetShaderResources(0, 2, inputs.data());
        context->Dispatch((static_cast<UINT>(data[1].size() / 8) + 63) / 64, 1, 1);
    }
    bound = nullptr;
    context->CSSetUnorderedAccessViews(0, 1, &bound, nullptr);
    output_desc.Usage = D3D11_USAGE_STAGING;
    output_desc.BindFlags = output_desc.MiscFlags = output_desc.StructureByteStride = 0;
    output_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ComPtr<ID3D11Buffer> staging;
    check(device->CreateBuffer(&output_desc, nullptr, &staging));
    context->CopyResource(staging.Get(), output.Get());
    D3D11_MAPPED_SUBRESOURCE mapped{};
    check(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped));
    std::ofstream file(std::filesystem::path(argv[4]), std::ios::binary);
    file.write(static_cast<const char*>(mapped.pData), output_desc.ByteWidth);
    context->Unmap(staging.Get(), 0);
    if (!file) throw std::runtime_error("Cannot write gathered bones");
}

int wmain(int argc, wchar_t** argv) {
    try {
        if (argc > 1 && std::wstring(argv[1]) == L"--gather") {
            gather(argc, argv);
            return 0;
        }
        if (argc != 6) throw std::runtime_error("skin_gpu shader rest blend bones output");
        const auto rest = read(argv[2]), blend = read(argv[3]), bones = read(argv[4]);
        if (rest.empty() || rest.size() % 40 || (blend.size() != rest.size() / 40 * 32 &&
                                                 blend.size() != rest.size() / 40 * 64) || bones.size() % 64)
            throw std::runtime_error("Invalid buffer size");
        ComPtr<ID3D11Device> device;
        ComPtr<ID3D11DeviceContext> context;
        check(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, nullptr, 0, D3D11_SDK_VERSION,
                               &device, nullptr, &context));
        ComPtr<ID3DBlob> code, errors;
        HRESULT hr = D3DCompileFromFile(argv[1], nullptr, D3D_COMPILE_STANDARD_FILE_INCLUDE, "main", "cs_5_0",
                                       D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &code, &errors);
        if (errors) std::cerr.write(static_cast<char*>(errors->GetBufferPointer()), errors->GetBufferSize());
        check(hr);
        ComPtr<ID3D11ComputeShader> shader;
        check(device->CreateComputeShader(code->GetBufferPointer(), code->GetBufferSize(), nullptr, &shader));
        std::array<ComPtr<ID3D11Buffer>, 3> inputs;
        std::array<ComPtr<ID3D11ShaderResourceView>, 3> views;
        const std::array<const std::vector<char>*, 3> data{&rest, &blend, &bones};
        for (unsigned i = 0; i < 3; ++i) {
            D3D11_BUFFER_DESC desc{};
            desc.ByteWidth = static_cast<UINT>(data[i]->size());
            desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
            desc.MiscFlags = i == 2 ? D3D11_RESOURCE_MISC_BUFFER_STRUCTURED : D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS;
            desc.StructureByteStride = i == 2 ? 64 : 0;
            D3D11_SUBRESOURCE_DATA initial{data[i]->data(), 0, 0};
            check(device->CreateBuffer(&desc, &initial, &inputs[i]));
            D3D11_SHADER_RESOURCE_VIEW_DESC view{};
            view.Format = i == 2 ? DXGI_FORMAT_UNKNOWN : DXGI_FORMAT_R32_TYPELESS;
            view.ViewDimension = D3D11_SRV_DIMENSION_BUFFEREX;
            view.BufferEx.NumElements = desc.ByteWidth / (i == 2 ? 64 : 4);
            view.BufferEx.Flags = i == 2 ? 0 : D3D11_BUFFEREX_SRV_FLAG_RAW;
            check(device->CreateShaderResourceView(inputs[i].Get(), &view, &views[i]));
        }
        D3D11_BUFFER_DESC output_desc{};
        output_desc.ByteWidth = static_cast<UINT>(rest.size());
        output_desc.BindFlags = D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_VERTEX_BUFFER;
        output_desc.MiscFlags = D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS;
        ComPtr<ID3D11Buffer> output;
        check(device->CreateBuffer(&output_desc, nullptr, &output));
        D3D11_UNORDERED_ACCESS_VIEW_DESC uav_desc{};
        uav_desc.Format = DXGI_FORMAT_R32_TYPELESS;
        uav_desc.ViewDimension = D3D11_UAV_DIMENSION_BUFFER;
        uav_desc.Buffer.NumElements = output_desc.ByteWidth / 4;
        uav_desc.Buffer.Flags = D3D11_BUFFER_UAV_FLAG_RAW;
        ComPtr<ID3D11UnorderedAccessView> uav;
        check(device->CreateUnorderedAccessView(output.Get(), &uav_desc, &uav));
        std::array<UINT, 4> config{static_cast<UINT>(rest.size() / 40), static_cast<UINT>(bones.size() / 64), 0, 0};
        D3D11_BUFFER_DESC cb_desc{};
        cb_desc.ByteWidth = 16;
        cb_desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        D3D11_SUBRESOURCE_DATA cb_data{config.data(), 0, 0};
        ComPtr<ID3D11Buffer> cb;
        check(device->CreateBuffer(&cb_desc, &cb_data, &cb));
        std::array<ID3D11ShaderResourceView*, 3> srv{views[0].Get(), views[1].Get(), views[2].Get()};
        ID3D11UnorderedAccessView* raw_uav = uav.Get();
        ID3D11Buffer* raw_cb = cb.Get();
        context->CSSetShader(shader.Get(), nullptr, 0);
        context->CSSetShaderResources(0, 3, srv.data());
        context->CSSetConstantBuffers(0, 1, &raw_cb);
        context->CSSetUnorderedAccessViews(0, 1, &raw_uav, nullptr);
        context->Dispatch((config[0] + 63) / 64, 1, 1);
        output_desc.Usage = D3D11_USAGE_STAGING;
        output_desc.BindFlags = output_desc.MiscFlags = 0;
        output_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        ComPtr<ID3D11Buffer> staging;
        check(device->CreateBuffer(&output_desc, nullptr, &staging));
        context->CopyResource(staging.Get(), output.Get());
        D3D11_MAPPED_SUBRESOURCE mapped{};
        check(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped));
        std::ofstream file(std::filesystem::path(argv[5]), std::ios::binary);
        file.write(static_cast<const char*>(mapped.pData), rest.size());
        context->Unmap(staging.Get(), 0);
        if (!file) throw std::runtime_error("Cannot write output");
        std::cout << "WARP skinning: " << config[0] << " vertices\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
