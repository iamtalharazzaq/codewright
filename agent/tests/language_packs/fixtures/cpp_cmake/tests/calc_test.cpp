#include <gtest/gtest.h>
#include "calc/calc.hpp"

TEST(Calc, Adds) { EXPECT_EQ(calc::add(2, 3), 5); }
TEST(Calc, Accumulates) {
  calc::Accumulator acc;
  acc.add(4);
  acc.add(-1);
  EXPECT_EQ(acc.total(), 3);
}
