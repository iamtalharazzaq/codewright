// {{title}}: {{description}}
#include <iostream>
#include <string>

#include "{{name_snake}}/{{name_snake}}.hpp"

int main() {
  std::cout << "{{title}} — type an expression (2 * 21), some words, or 'quit'.\n";
  std::string line;
  while (std::cout << "> " << std::flush, std::getline(std::cin, line)) {
    if (line == "quit" || line == "exit" || line == "q") {
      std::cout << "Bye!\n";
      return 0;
    }
    std::cout << {{name_snake}}::respond(line) << '\n';
  }
  std::cout << '\n';
  return 0;
}
