#include <gtest/gtest.h>

#include "miniapp/core.hpp"

TEST(Core, Greets) {
  EXPECT_EQ(miniapp::greet("Ada"), "Hello, Ada!");
  EXPECT_EQ(miniapp::greet("  "), "Hello, world!");
}

TEST(Core, CountsWords) {
  auto counts = miniapp::word_count("b a b. C c c");
  EXPECT_EQ(counts["c"], 3);
  EXPECT_EQ(counts["b"], 2);
  EXPECT_EQ(counts["a"], 1);
}
