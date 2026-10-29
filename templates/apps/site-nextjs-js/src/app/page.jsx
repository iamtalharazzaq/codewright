import Link from "next/link";
import { site } from "../site";

const features = [
  { title: "Fast", text: "Pages are rendered on the server and sent ready to read." },
  { title: "Found", text: "Titles, descriptions, a sitemap and robots.txt are already set up." },
  { title: "For everyone", text: "Works on phones, in dark mode, and with a keyboard." },
];

export default function Home() {
  return (
    <>
      <section className="hero">
        <h1>{site.name}</h1>
        <p>{site.description}</p>
        <Link className="button" href="/about">Learn more</Link>
      </section>
      <ul className="features">
        {features.map((f) => (
          <li key={f.title}>
            <h2>{f.title}</h2>
            <p>{f.text}</p>
          </li>
        ))}
      </ul>
    </>
  );
}
