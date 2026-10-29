"use client";

import { useEffect, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { disconnectDrive, getConnectors, type Connectors } from "@/lib/api";

/** Settings → Google Drive (ADR 0018): connect with your own OAuth client; the token is stored encrypted. */
export function DriveCard() {
  const [info, setInfo] = useState<Connectors | null>(null);
  const load = () =>
    getConnectors()
      .then(setInfo)
      .catch(() => setInfo(null));

  useEffect(() => {
    void load();
  }, []);

  const drive = info?.drive;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Google Drive</CardTitle>
        <CardDescription>
          Import a project from a Drive ZIP link and deliver results to Drive.{" "}
          {drive?.connected ? "Connected." : "Not connected."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {drive && !drive.configured && <p className="text-sm text-muted-foreground">{drive.problem}</p>}
        <div className="flex gap-2">
          {drive?.connected ? (
            <Button variant="outline" onClick={() => void disconnectDrive().then(load)}>
              Disconnect
            </Button>
          ) : (
            drive?.configured && (
              // A plain link: the API redirects to Google's consent page and back to Settings.
              <a href="/api/connectors/gdrive/start" className={buttonVariants()}>
                Connect Google Drive
              </a>
            )
          )}
        </div>
        {drive?.connected && (
          <p className="text-sm text-muted-foreground">
            Disconnect removes Codewright&apos;s local copy of your Drive token. Google still remembers the grant until
            you revoke it yourself at{" "}
            <a href="https://myaccount.google.com/permissions" target="_blank" rel="noreferrer" className="underline">
              myaccount.google.com/permissions
            </a>
            .
          </p>
        )}
      </CardContent>
    </Card>
  );
}
