const ROLE_LABEL: Record<string, string> = {
  project_manager: "Project Manager",
  business_analyst: "Business Analyst",
  qa_engineer: "QA Engineer",
  solution_architect: "Solution Architect",
  technical_writer: "Technical Writer",
  devops_engineer: "DevOps Engineer",
  backend_developer: "Backend Developer",
  database_engineer: "Database Engineer",
  frontend_developer: "Frontend Developer",
  release_manager: "Release Manager",
};

/** "product_manager" → "Product Manager": a role without a hand-written label is still shown without underscores. */
export function roleLabel(role: string): string {
  return (
    ROLE_LABEL[role] ??
    role
      .split("_")
      .filter(Boolean)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ")
  );
}
