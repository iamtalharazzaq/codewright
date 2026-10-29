import { absoluteUrl, site } from "../site";

export default function sitemap() {
  return site.nav.map((item) => ({ url: absoluteUrl(item.href) }));
}
