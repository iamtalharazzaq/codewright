#include <gtest/gtest.h>

#include "{{name_snake}}/{{name_snake}}.hpp"

using namespace {{name_snake}};

TEST(Evaluate, Arithmetic) {
  EXPECT_DOUBLE_EQ(*evaluate("2 * 21"), 42);
  EXPECT_DOUBLE_EQ(*evaluate("1.5+1.5"), 3);
  EXPECT_DOUBLE_EQ(*evaluate("10 / 4"), 2.5);
}

TEST(Evaluate, RejectsWhatIsNotAnExpression) {
  EXPECT_FALSE(evaluate("hello there"));
  EXPECT_FALSE(evaluate("1 / 0"));
  EXPECT_FALSE(evaluate("1 + 2 extra"));
}

TEST(Respond, CountsWords) {
  EXPECT_EQ(respond("one two three"), "3 words");
  EXPECT_EQ(respond("one"), "1 word");
  EXPECT_EQ(respond("6 - 1"), "= 5");
}
