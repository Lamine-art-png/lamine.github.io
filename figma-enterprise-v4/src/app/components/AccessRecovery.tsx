import { FormEvent, useMemo, useState } from "react";
import { ArrowLeft, CheckCircle2, KeyRound, Loader2 } from "lucide-react";
import { recoveryClient } from "../api/recoveryClient";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-10" style={{ background: "#EEE9DB" }}>
      <div className="w-full max-w-[460px] rounded-[20px] border border-[rgba(16,35,27,0.1)] bg-[#FFFDF8] p-7 shadow-[0_24px_70px_rgba(16,35,27,0.12)]">
        {children}
      </div>
    </div>
  );
}

function Intro({ title, body }: { title: string; body: string }) {
  return (
    <div className="mb-5">
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-[#E8F0E3] text-[#1E5B40]">
        <KeyRound className="h-5 w-5" />
      </div>
      <h1 className="text-[20px] font-semibold text-[#10231B]">{title}</h1>
      <p className="mt-2 text-[13px] leading-6 text-[#65736A]">{body}</p>
    </div>
  );
}

export function AccessRecoveryPage() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const token = params.get("token") || "";
  const [email, setEmail] = useState("");
  const [credential, setCredential] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setWorking(true);
    try {
      const response = await recoveryClient.start({ email });
      setMessage(response.message || "If an account exists, recovery instructions were sent.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request could not be processed.");
    } finally {
      setWorking(false);
    }
  }

  async function complete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (credential !== confirmation) {
      setError("The entries do not match.");
      return;
    }
    if (credential.length < 12) {
      setError("Use at least 12 characters.");
      return;
    }
    setWorking(true);
    try {
      const response = await recoveryClient.complete({ token, replacement_credential: credential });
      setMessage(response.message || "Account access updated.");
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The recovery link is invalid or expired.");
    } finally {
      setWorking(false);
    }
  }

  if (done) {
    return (
      <Card>
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[#E8F0E3] text-[#2D6A4F]">
          <CheckCircle2 className="h-6 w-6" />
        </div>
        <h1 className="mt-5 text-[20px] font-semibold text-[#10231B]">Account access updated</h1>
        <p className="mt-2 text-[13px] leading-6 text-[#65736A]">{message}</p>
        <Button type="button" onClick={() => { window.location.href = "/"; }} className="mt-5 w-full bg-[#10231B] text-white">
          Return to sign in
        </Button>
      </Card>
    );
  }

  return (
    <Card>
      {token ? (
        <>
          <Intro title="Choose a new sign-in credential" body="Use at least 12 characters. Completing recovery invalidates older sessions." />
          <form className="space-y-4" onSubmit={complete}>
            <Input type="password" aria-label="New sign-in credential" value={credential} onChange={(event) => setCredential(event.target.value)} minLength={12} required />
            <Input type="password" aria-label="Confirm sign-in credential" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} minLength={12} required />
            <Button type="submit" disabled={working} className="w-full bg-[#10231B] text-white">
              {working ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Update account access
            </Button>
          </form>
        </>
      ) : (
        <>
          <Intro title="Recover account access" body="Enter your email. For privacy, the response is the same whether or not an account exists." />
          <form className="space-y-4" onSubmit={start}>
            <Input type="email" aria-label="Email" value={email} onChange={(event) => setEmail(event.target.value)} required />
            <Button type="submit" disabled={working} className="w-full bg-[#10231B] text-white">
              {working ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Send recovery instructions
            </Button>
          </form>
        </>
      )}

      {message ? <div className="mt-4 rounded-md border border-[#D7E4CF] bg-[#F6FAF1] px-3 py-3 text-sm text-[#375347]">{message}</div> : null}
      {error ? <div className="mt-4 rounded-md border border-[#B94A48]/25 bg-[#B94A48]/8 px-3 py-2 text-sm text-[#7A2E2B]">{error}</div> : null}
      <button type="button" onClick={() => { window.location.href = "/"; }} className="mt-5 inline-flex items-center gap-2 text-[13px] font-medium text-[#2D6A4F]">
        <ArrowLeft className="h-4 w-4" /> Back to sign in
      </button>
    </Card>
  );
}
