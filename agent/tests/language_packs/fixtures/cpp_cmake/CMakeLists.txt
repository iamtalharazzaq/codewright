cmake_minimum_required(VERSION 3.20)
project(calc LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)

add_library(calc_core src/calc.cpp)
target_include_directories(calc_core PUBLIC include)

add_executable(calc src/main.cpp)
target_link_libraries(calc PRIVATE calc_core)

enable_testing()
add_subdirectory(tests)
