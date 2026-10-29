#include "{{name_snake}}/{{name_snake}}.hpp"

#include <cctype>
#include <stdexcept>

namespace {{name_snake}} {

std::string slugify(std::string_view text) {
  std::string out;
  bool pending_dash = false;
  for (unsigned char c : text) {
    if (std::isalnum(c)) {
      if (pending_dash && !out.empty()) out += '-';
      pending_dash = false;
      out += static_cast<char>(std::tolower(c));
    } else {
      pending_dash = true;
    }
  }
  return out;
}

std::string truncate(std::string_view text, std::size_t limit, std::string_view ellipsis) {
  if (limit < ellipsis.size()) throw std::invalid_argument("limit is shorter than the ellipsis");
  if (text.size() <= limit) return std::string(text);
  return std::string(text.substr(0, limit - ellipsis.size())) + std::string(ellipsis);
}

}  // namespace {{name_snake}}
