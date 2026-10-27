import type { Metadata } from "next";
import { Suspense } from "react";

import { ChatView } from "@/components/chat/chat-view";

export const metadata: Metadata = { title: "Chat" };

// Cache Components: read the dynamic param inside <Suspense> so the shell can still prerender.
export default function ConversationPage({ params }: PageProps<"/c/[id]">) {
  return (
    <Suspense fallback={<ChatView />}>
      <Conversation params={params} />
    </Suspense>
  );
}

async function Conversation({ params }: Pick<PageProps<"/c/[id]">, "params">) {
  const { id } = await params;
  return <ChatView key={id} conversationId={id} />;
}
