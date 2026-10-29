import { absoluteUrl } from "../site";

export default function robots() {
  return { rules: { userAgent: "*", allow: "/" }, sitemap: absoluteUrl("/sitemap.xml") };
}
