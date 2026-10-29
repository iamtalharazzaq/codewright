#pragma once
#include <map>
#include <string>
#include <vector>

namespace miniapp {

std::string greet(const std::string& name);
std::map<std::string, int> word_count(const std::string& text);
double avg(const std::vector<double>& nums);

}  // namespace miniapp
