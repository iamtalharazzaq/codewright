#include <iostream>
#include <string>
#include "calc/calc.hpp"

int main() {
  calc::Accumulator acc;
  std::cout << "Running total. Type numbers, or 'quit'.\n";
  std::string line;
  while (std::cout << "> " << std::flush, std::getline(std::cin, line)) {
    if (line == "quit") break;
    try {
      acc.add(std::stoi(line));
      std::cout << "total = " << acc.total() << '\n';
    } catch (...) {
      std::cout << "not a number\n";
    }
  }
  std::cout << "bye, total " << acc.total() << '\n';
}
