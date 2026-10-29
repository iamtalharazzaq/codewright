import type { Metadata } from "next";

export const metadata: Metadata = { title: "About" };

export default function About() {
  return (
    <section className="hero">
      <h1>About</h1>
      <p>Tell visitors who you are and what you do. Edit this page in src/app/about/page.tsx.</p>
    </section>
  );
}
