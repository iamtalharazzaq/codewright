cmake_minimum_required(VERSION 3.20)
project(miniapp LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)

add_library(miniapp_core src/core.cpp)
target_include_directories(miniapp_core PUBLIC include)

enable_testing()
add_subdirectory(tests)
