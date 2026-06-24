import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { formatApiError } from "@/lib/api";
import { Activity } from "lucide-react";

export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await register(email, password, name);
      nav("/");
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-[#F9FAFB]">
      <div className="w-full max-w-md brut-card p-8" data-testid="register-card">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-10 h-10 bg-[#002FA7] brut-border flex items-center justify-center">
            <Activity size={22} className="text-white" />
          </div>
          <div className="font-head font-black text-3xl tracking-tighter leading-none">
            VINTED<span className="text-[#FF3B30]">.</span>BOT
          </div>
        </div>
        <h1 className="font-head text-3xl font-black tracking-tighter mb-1">Create Account</h1>
        <p className="font-mono text-xs uppercase tracking-widest text-gray-600 mb-6">// initialize new operator</p>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="brut-label">Display Name</label>
            <input data-testid="reg-name-input" value={name} onChange={(e) => setName(e.target.value)} className="brut-input" placeholder="Your name" />
          </div>
          <div>
            <label className="brut-label">Email</label>
            <input data-testid="reg-email-input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="brut-input" placeholder="user@example.com" />
          </div>
          <div>
            <label className="brut-label">Password (min 6 chars)</label>
            <input data-testid="reg-password-input" type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} className="brut-input" placeholder="••••••••" />
          </div>
          {error && (
            <div data-testid="register-error" className="brut-border bg-[#FF3B30] text-white font-mono text-xs p-3 uppercase">{error}</div>
          )}
          <button data-testid="register-submit-btn" disabled={loading} type="submit" className="brut-btn w-full">
            {loading ? "Creating..." : "Create Account"}
          </button>
        </form>

        <div className="mt-6 font-mono text-xs uppercase tracking-widest text-center">
          Have an account?{" "}
          <Link to="/login" className="text-[#002FA7] font-bold underline" data-testid="goto-login">Sign in</Link>
        </div>
      </div>
    </div>
  );
}
