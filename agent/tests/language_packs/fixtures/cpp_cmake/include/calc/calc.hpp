#pragma once
namespace calc {
class Accumulator {
 public:
  void add(int value) { total_ += value; }
  int total() const { return total_; }
 private:
  int total_ = 0;
};
int add(int a, int b);
}  // namespace calc
