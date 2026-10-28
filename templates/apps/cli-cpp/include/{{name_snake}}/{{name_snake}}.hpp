// {{title}}: the logic, kept apart from input/output so it can be tested.
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace {{name_snake}} {

// A tiny calculator over "a op b" (op is one of + - * /). Empty when the line isn't an expression.
std::optional<double> evaluate(const std::string& line);

// The words of a line, split on whitespace.
std::vector<std::string> words(const std::string& line);

// What the console prints back for one line of input.
std::string respond(const std::string& line);

}  // namespace {{name_snake}}
