import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
} from "@/components/ui/input-otp";

import { useAuth } from "@/hooks/use-auth";
import { ArrowRight, Loader2, Mail, UserX } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import Polyhedron from "@/components/Polyhedron";

interface AuthProps {
  redirectAfterAuth?: string;
}

function resolveRedirectAfterAuth(
  returnTo: string | null,
  fallback = "/dashboard",
) {
  if (returnTo?.startsWith("/") && !returnTo.startsWith("//")) {
    return returnTo;
  }
  return fallback;
}

function Auth({ redirectAfterAuth }: AuthProps = {}) {
  const { isLoading: authLoading, isAuthenticated, signIn } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const redirect = resolveRedirectAfterAuth(
    searchParams.get("returnTo"),
    redirectAfterAuth,
  );
  const [step, setStep] = useState<"signIn" | { email: string }>("signIn");
  const [otp, setOtp] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && isAuthenticated) {
      navigate(redirect);
    }
  }, [authLoading, isAuthenticated, navigate, redirect]);

  const handleEmailSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      const formData = new FormData(event.currentTarget);
      await signIn("email-otp", formData);
      setStep({ email: formData.get("email") as string });
      setIsLoading(false);
    } catch (error) {
      console.error("Email sign-in error:", error);
      setError(
        error instanceof Error
          ? error.message
          : "Failed to send verification code. Please try again.",
      );
      setIsLoading(false);
    }
  };

  const handleOtpSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      const formData = new FormData(event.currentTarget);
      await signIn("email-otp", formData);
      navigate(redirect);
    } catch (error) {
      console.error("OTP verification error:", error);
      setError("The verification code you entered is incorrect.");
      setIsLoading(false);
      setOtp("");
    }
  };

  const handleGuestLogin = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await signIn("anonymous");
      navigate(redirect);
    } catch (error) {
      console.error("Guest login error:", error);
      setError(
        `Failed to sign in as guest: ${
          error instanceof Error ? error.message : "Unknown error"
        }`,
      );
      setIsLoading(false);
    }
  };

  return (
    <div className="ptg-stars flex min-h-screen flex-col items-center justify-center gap-8 p-4">
      <button
        onClick={() => navigate("/")}
        className="flex items-center gap-3"
        aria-label="Back to home"
      >
        <Polyhedron size={36} glow={false} />
        <span className="text-sm font-semibold uppercase tracking-[0.35em]">
          Pentagon
        </span>
      </button>

      <div className="w-full max-w-sm rounded-2xl bg-card/70 ptg-border shadow-2xl shadow-black/40 backdrop-blur-xl">
        <div className="flex items-center justify-between gap-2 rounded-t-2xl px-5 py-3.5 ptg-border-b">
          <p className="text-xs font-medium tracking-wide text-muted-foreground">
            {step === "signIn" ? "Get started" : "Check your email"}
          </p>
          <p className="text-xs font-medium uppercase tracking-[0.25em] text-muted-foreground/70">
            Pentagon
          </p>
        </div>

        {step === "signIn" ? (
          <form onSubmit={handleEmailSubmit}>
            <div className="flex flex-col gap-4 p-6">
              <p className="text-sm text-muted-foreground">
                Enter your email to log in or sign up.
              </p>
              <div className="relative flex items-center">
                <Mail className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  name="email"
                  placeholder="name@example.com"
                  type="email"
                  className="rounded-xl border-border bg-background/60 pl-9 font-medium"
                  disabled={isLoading}
                  required
                />
              </div>
              {error && (
                <p className="rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  {error}
                </p>
              )}
              <Button
                type="submit"
                className="w-full rounded-full bg-primary font-medium text-primary-foreground hover:bg-primary/90"
                disabled={isLoading}
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    Send code
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </Button>

              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t border-border" />
                </div>
                <div className="relative flex justify-center">
                  <span className="bg-card/70 px-2 text-[10px] font-medium uppercase tracking-[0.25em] text-muted-foreground">
                    Or
                  </span>
                </div>
              </div>

              <Button
                type="button"
                variant="outline"
                className="w-full rounded-full border-border bg-transparent font-medium hover:bg-accent"
                onClick={handleGuestLogin}
                disabled={isLoading}
              >
                <UserX className="mr-2 h-4 w-4" />
                Continue as Guest
              </Button>
            </div>
          </form>
        ) : (
          <form onSubmit={handleOtpSubmit}>
            <div className="flex flex-col gap-4 p-6">
              <p className="text-sm text-muted-foreground">
                We&apos;ve sent a 6-digit code to{" "}
                <span className="rounded-full bg-primary/10 px-2 py-0.5 font-medium text-primary">
                  {step.email}
                </span>
                . Enter it below.
              </p>
              <input type="hidden" name="email" value={step.email} />
              <input type="hidden" name="code" value={otp} />

              <div className="flex justify-center">
                <InputOTP
                  value={otp}
                  onChange={setOtp}
                  maxLength={6}
                  disabled={isLoading}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      otp.length === 6 &&
                      !isLoading
                    ) {
                      const form = (e.target as HTMLElement).closest("form");
                      if (form) {
                        form.requestSubmit();
                      }
                    }
                  }}
                >
                  <InputOTPGroup>
                    {Array.from({ length: 6 }).map((_, index) => (
                      <InputOTPSlot key={index} index={index} />
                    ))}
                  </InputOTPGroup>
                </InputOTP>
              </div>
              {error && (
                <p className="rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-center text-xs text-destructive">
                  {error}
                </p>
              )}
              <Button
                type="submit"
                className="w-full rounded-full bg-primary font-medium text-primary-foreground hover:bg-primary/90"
                disabled={isLoading || otp.length !== 6}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Verifying...
                  </>
                ) : (
                  <>
                    Verify code
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </>
                )}
              </Button>
              <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-widest">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setStep("signIn")}
                  disabled={isLoading}
                  className="h-auto p-0 text-muted-foreground hover:text-foreground"
                >
                  Use different email
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setStep("signIn")}
                  disabled={isLoading}
                  className="h-auto p-0 text-muted-foreground hover:text-foreground"
                >
                  Resend
                </Button>
              </div>
            </div>
          </form>
        )}

        <div className="rounded-b-2xl ptg-border-t bg-background/40 px-6 py-3 text-center text-[10px] font-medium uppercase tracking-[0.25em] text-muted-foreground">
          Secured by Convex Auth
        </div>
      </div>
    </div>
  );
}

export default function AuthPage(props: AuthProps) {
  return (
    <Suspense>
      <Auth {...props} />
    </Suspense>
  );
}
