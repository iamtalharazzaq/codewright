#pragma once
// {{title}}: {{description}}

#include <string>
#include <string_view>

namespace {{name_snake}} {

// Lower-cases text and joins its words with dashes: "Hello, World!" becomes "hello-world".
std::string slugify(std::string_view text);

// Cuts text to at most `limit` bytes, ending with `ellipsis` when something was cut.
// Throws std::invalid_argument when the limit is shorter than the ellipsis.
std::string truncate(std::string_view text, std::size_t limit, std::string_view ellipsis = "...");

}  // namespace {{name_snake}}
