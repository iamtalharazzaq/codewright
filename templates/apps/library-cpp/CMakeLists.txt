cmake_minimum_required(VERSION 3.20)
project({{name_snake}} VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_library({{name_snake}} src/{{name_snake}}.cpp)
add_library({{name_snake}}::{{name_snake}} ALIAS {{name_snake}})
target_include_directories({{name_snake}} PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
target_compile_options({{name_snake}} PRIVATE -Wall -Wextra -Wpedantic)

install(TARGETS {{name_snake}} EXPORT {{name_snake}}-targets ARCHIVE DESTINATION lib)
install(DIRECTORY include/ DESTINATION include)
install(EXPORT {{name_snake}}-targets NAMESPACE {{name_snake}}:: DESTINATION lib/cmake/{{name_snake}})

include(CTest)
if(BUILD_TESTING)
  find_package(GTest REQUIRED)
  add_executable({{name_snake}}_tests tests/{{name_snake}}_test.cpp)
  target_link_libraries({{name_snake}}_tests PRIVATE {{name_snake}}::{{name_snake}} GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests({{name_snake}}_tests)
endif()
