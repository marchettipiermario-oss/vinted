import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { formatApiError } from "@/lib/api";
import { Activity } from "lucide-react";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      nav("/");
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-[#F9FAFB]">
      <div className="w-full max-w-md brut-card p-8" data-testid="login-card">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-10 h-10 bg-[#002FA7] brut-border flex items-center justify-center">
            <Activity size={22} className="text-white" />
          </div>
          <div className="font-head font-black text-3xl tracking-tighter leading-none">
            VINTED<span className="text-[#FF3B30]">.</span>BOT
          </div>
        </div>
        <h1 className="font-head text-3xl font-black tracking-tighter mb-1">Access Terminal</h1>
        <p className="font-mono text-xs uppercase tracking-widest text-gray-600 mb-6">// authenticate to begin operations</p>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="brut-label">Email</label>
            <input
              data-testid="login-email-input"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="brut-input"
              placeholder="user@example.com"
            />
          </div>
          <div>
            <label className="brut-label">Password</label>
            <input
              data-testid="login-password-input"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="brut-input"
              placeholder="••••••••"
            />
          </div>
          {error && (
            <div data-testid="login-error" className="brut-border bg-[#FF3B30] text-white font-mono text-xs p-3 uppercase">
              {error}
            </div>
          )}
          <button
            data-testid="login-submit-btn"
            disabled={loading}
            type="submit"
            className="brut-btn w-full"
          >
            {loading ? "Authenticating..." : "Sign In"}
          </button>
        </form>

        <div className="mt-6 font-mono text-xs uppercase tracking-widest text-center">
          No account?{" "}
          <Link to="/register" className="text-[#002FA7] font-bold underline" data-testid="goto-register">
            Register
          </Link>
        </div>
      </div>
    </div>
  );
}
