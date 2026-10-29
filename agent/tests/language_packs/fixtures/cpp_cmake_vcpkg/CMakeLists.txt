cmake_minimum_required(VERSION 3.20)
project(greet LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)

find_package(fmt CONFIG REQUIRED)

add_executable(greet src/main.cpp)
target_link_libraries(greet PRIVATE fmt::fmt)
