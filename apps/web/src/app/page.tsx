import { Suspense } from "react";

import { ChatView } from "@/components/chat/chat-view";

// `/?project=<id>` starts a chat inside that project. Read inside <Suspense> (Cache Components).
export default function ChatPage({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<ChatView />}>
      <NewChat searchParams={searchParams} />
    </Suspense>
  );
}

async function NewChat({ searchParams }: Pick<PageProps<"/">, "searchParams">) {
  const { project } = await searchParams;
  const projectId = typeof project === "string" ? project : null;
  return <ChatView key={projectId ?? "none"} projectId={projectId} />;
}
