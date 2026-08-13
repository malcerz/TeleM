cmake_minimum_required(VERSION 3.15)
project(d3d11_amf_pipeline_poc LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

add_executable(d3d11_etap2c_poc
    src/main_etap2c.cpp
    src/d3d11_vp_pipeline.cpp
    src/d3d11_vp_pipeline.h
    src/d3d11_amf_encoder.cpp
    src/d3d11_amf_encoder.h
)

target_link_libraries(d3d11_etap2c_poc PRIVATE
    d3d11.lib
    dxgi.lib
    d3dcompiler.lib
)

if(MSVC)
    target_compile_options(d3d11_etap2c_poc PRIVATE /W4 /O2)
endif()
