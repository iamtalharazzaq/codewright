import type { MetadataRoute } from "next";
import { absoluteUrl, site } from "../site";

export default function sitemap(): MetadataRoute.Sitemap {
  return site.nav.map((item) => ({ url: absoluteUrl(item.href) }));
}
