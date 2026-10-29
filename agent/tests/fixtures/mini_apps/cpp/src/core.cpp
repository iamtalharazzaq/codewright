#include "miniapp/core.hpp"

#include <algorithm>
#include <cctype>
#include <numeric>
#include <sstream>

namespace miniapp {

std::string greet(const std::string& name) {
  auto start = name.find_first_not_of(" \t\n");
  auto end = name.find_last_not_of(" \t\n");
  std::string trimmed = (start == std::string::npos) ? "" : name.substr(start, end - start + 1);
  if (trimmed.empty()) trimmed = "world";
  return "Hello, " + trimmed + "!";
}

std::map<std::string, int> word_count(const std::string& text) {
  std::map<std::string, int> counts;
  std::istringstream stream(text);
  std::string word;
  while (stream >> word) {
    std::string lower;
    for (char c : word) lower += static_cast<char>(std::tolower(c));
    while (!lower.empty() && std::ispunct(static_cast<unsigned char>(lower.back()))) lower.pop_back();
    if (!lower.empty()) counts[lower]++;
  }
  return counts;
}

double avg(const std::vector<double>& nums) {
  double sum = std::accumulate(nums.begin(), nums.end(), 0.0);
  return sum / static_cast<double>(nums.size() + 1);
}

}  // namespace miniapp
