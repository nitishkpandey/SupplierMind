import { useTranslation } from "react-i18next";
import { Brain, Github } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

// Google icon as SVG (lucide doesn't have Google)
function GoogleIcon() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
    </svg>
  );
}

export default function LoginPage() {
  const { t } = useTranslation();

  const handleGoogleLogin = () => {
    window.location.href = "http://localhost:8000/api/v1/auth/google/authorize";
  };

  const handleGithubLogin = () => {
    window.location.href = "http://localhost:8000/api/v1/auth/github/authorize";
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
      {/* Background pattern */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#4f4f4f2e_1px,transparent_1px),linear-gradient(to_bottom,#4f4f4f2e_1px,transparent_1px)] bg-[size:14px_24px]" />

      <div className="relative w-full max-w-md space-y-6">
        {/* Logo */}
        <div className="text-center space-y-3">
          <div className="mx-auto w-16 h-16 rounded-2xl bg-primary flex items-center justify-center shadow-2xl">
            <Brain className="w-9 h-9 text-white" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-white">{t("app_name")}</h1>
            <p className="text-slate-400 mt-1">{t("tagline")}</p>
          </div>
        </div>

        {/* Login card */}
        <Card className="border-slate-700 bg-slate-800/80 backdrop-blur-sm">
          <CardHeader className="text-center">
            <CardTitle className="text-white">{t("auth.sign_in_title")}</CardTitle>
            <CardDescription className="text-slate-400">
              {t("auth.sign_in_subtitle")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button
              onClick={handleGoogleLogin}
              variant="outline"
              className="w-full h-11 gap-3 bg-white hover:bg-slate-50 text-slate-900 border-white"
            >
              <GoogleIcon />
              {t("auth.google")}
            </Button>

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-slate-600" />
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="px-2 bg-slate-800 text-slate-400">{t("auth.or")}</span>
              </div>
            </div>

            <Button
              onClick={handleGithubLogin}
              variant="outline"
              className="w-full h-11 gap-3 bg-slate-900 hover:bg-slate-800 text-white border-slate-600"
            >
              <Github className="w-5 h-5" />
              {t("auth.github")}
            </Button>
          </CardContent>
        </Card>

        {/* Footer */}
        <p className="text-center text-xs text-slate-500">
          Master's Thesis · Gisma University of Applied Sciences · Mercanis GmbH
        </p>
      </div>
    </div>
  );
}
