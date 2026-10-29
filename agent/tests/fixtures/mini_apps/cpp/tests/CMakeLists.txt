find_package(GTest REQUIRED)
# Globbed, not listed by name: Codewright's own test file for a source file lands next to it
# (own_test_file, agent/playbooks/code_edit.py), e.g. src/core_codewright_test.cpp, not under tests/.
# CONFIGURE_DEPENDS re-globs on the next fresh configure, which is all this throwaway build ever does.
file(GLOB TEST_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/../src/*_codewright_test.cpp"
)
add_executable(miniapp_tests ${TEST_SOURCES})
target_link_libraries(miniapp_tests PRIVATE miniapp_core GTest::gtest_main)
include(GoogleTest)
gtest_discover_tests(miniapp_tests)
