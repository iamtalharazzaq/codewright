#include <gtest/gtest.h>

#include <stdexcept>

#include "{{name_snake}}/{{name_snake}}.hpp"

TEST(Slugify, JoinsWordsWithDashes) {
  EXPECT_EQ({{name_snake}}::slugify("Hello, World!"), "hello-world");
  EXPECT_EQ({{name_snake}}::slugify("  --  "), "");
}

TEST(Truncate, LeavesShortTextAlone) { EXPECT_EQ({{name_snake}}::truncate("short", 10), "short"); }

TEST(Truncate, CutsLongText) { EXPECT_EQ({{name_snake}}::truncate("a longer sentence", 8), "a lon..."); }

TEST(Truncate, RejectsATinyLimit) { EXPECT_THROW({{name_snake}}::truncate("anything", 1), std::invalid_argument); }
