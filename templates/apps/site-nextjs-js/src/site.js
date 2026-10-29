/** Everything that names the site, in one place. */
export const site = {
  name: "{{title}}",
  description: "{{description}}",
  url: process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  nav: [
    { href: "/", label: "Home" },
    { href: "/about", label: "About" },
  ],
};

/** The full address of a path on this site. */
export function absoluteUrl(path) {
  return new URL(path, site.url).toString();
}
