#include <iostream>
#include <nlohmann/json.hpp>

int main() {
  nlohmann::json greeting = {{"hello", "conan"}};
  std::cout << greeting.dump() << "\n";
}
