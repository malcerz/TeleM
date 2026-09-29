cmake_minimum_required(VERSION 3.15)
project(d3d11_compositor LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(d3d11_compositor_poc
    src/main.cpp
    src/d3d11_compositor.cpp
    src/d3d11_compositor.h
)

target_link_libraries(d3d11_compositor_poc PRIVATE
    d3d11.lib
    dxgi.lib
    d3dcompiler.lib
)

target_include_directories(d3d11_compositor_poc PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

if(MSVC)
    target_compile_options(d3d11_compositor_poc PRIVATE /W4 /O2)
endif()
