#include "{{name_snake}}/{{name_snake}}.hpp"

#include <cmath>
#include <sstream>

namespace {{name_snake}} {

std::optional<double> evaluate(const std::string& line) {
  std::istringstream in(line);
  double a = 0;
  double b = 0;
  char op = 0;
  if (!(in >> a >> op >> b)) return std::nullopt;
  std::string rest;
  if (in >> rest) return std::nullopt;
  switch (op) {
    case '+': return a + b;
    case '-': return a - b;
    case '*': return a * b;
    case '/':
      if (b == 0) return std::nullopt;
      return a / b;
    default: return std::nullopt;
  }
}

std::vector<std::string> words(const std::string& line) {
  std::istringstream in(line);
  std::vector<std::string> out;
  for (std::string w; in >> w;) out.push_back(w);
  return out;
}

std::string respond(const std::string& line) {
  if (auto value = evaluate(line)) {
    std::ostringstream out;
    out << "= " << *value;
    return out.str();
  }
  auto w = words(line);
  if (w.empty()) return "Type an expression like 2 * 21, some words, or 'quit'.";
  return std::to_string(w.size()) + (w.size() == 1 ? " word" : " words");
}

}  // namespace {{name_snake}}
