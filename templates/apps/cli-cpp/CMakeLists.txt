cmake_minimum_required(VERSION 3.20)
project({{name_snake}} VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_library({{name_snake}}_lib src/{{name_snake}}.cpp)
target_include_directories({{name_snake}}_lib PUBLIC include)
target_compile_options({{name_snake}}_lib PRIVATE -Wall -Wextra -Wpedantic)

add_executable({{name}} src/main.cpp)
target_link_libraries({{name}} PRIVATE {{name_snake}}_lib)

include(CTest)
if(BUILD_TESTING)
  find_package(GTest REQUIRED)
  add_executable({{name_snake}}_tests tests/{{name_snake}}_test.cpp)
  target_link_libraries({{name_snake}}_tests PRIVATE {{name_snake}}_lib GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests({{name_snake}}_tests)
endif()
