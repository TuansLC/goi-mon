/**
 * Kitchen Login Page.
 * - Input for restaurant slug and PIN
 * - On success, stores JWT and navigates to kitchen board
 * - If PIN not required, allows skipping PIN input
 */

import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { staffLogin, getWsTicket } from "./api";
import { useKitchenAuth } from "./AuthContext";

export default function KitchenLoginPage() {
  const { slug: paramSlug } = useParams<{ slug?: string }>();
  const [slug, setSlug] = useState(paramSlug || "");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [pinRequired, setPinRequired] = useState<boolean | null>(null);
  const navigate = useNavigate();
  const { setAuth } = useKitchenAuth();

  // Check if PIN is required by attempting anonymous ws-ticket
  const checkPinRequired = async () => {
    if (!slug.trim()) {
      setError("Vui lòng nhập slug quán");
      return;
    }
    setLoading(true);
    setError("");
    try {
      // Try getting ticket without JWT (anonymous)
      await getWsTicket(slug.trim(), null);
      // Success → PIN not required, go directly to board
      setPinRequired(false);
      setAuth(null, slug.trim());
      navigate(`/${slug.trim()}/kitchen/board`, { replace: true });
    } catch {
      // Failed → PIN is required
      setPinRequired(true);
    } finally {
      setLoading(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!slug.trim()) {
      setError("Vui lòng nhập slug quán");
      return;
    }
    if (pinRequired !== false && !pin.trim()) {
      setError("Vui lòng nhập PIN");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const { access_token } = await staffLogin(slug.trim(), pin.trim());
      setAuth(access_token, slug.trim());
      navigate(`/${slug.trim()}/kitchen/board`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đăng nhập thất bại");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center p-4">
      <div className="bg-gray-800 rounded-2xl shadow-xl p-8 w-full max-w-sm">
        <h1 className="text-2xl font-bold text-white text-center mb-6">
          🍳 Bếp QOrder
        </h1>

        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label className="block text-gray-300 text-sm mb-1">Slug quán</label>
            <input
              type="text"
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                setPinRequired(null);
              }}
              placeholder="vd: quan-bia-abc"
              className="w-full px-4 py-3 rounded-lg bg-gray-700 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-500"
              autoFocus={!paramSlug}
            />
          </div>

          {pinRequired === null && (
            <button
              type="button"
              onClick={checkPinRequired}
              disabled={loading}
              className="w-full py-3 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold disabled:opacity-50 transition-colors"
            >
              {loading ? "Đang kiểm tra..." : "Tiếp tục"}
            </button>
          )}

          {pinRequired === true && (
            <>
              <div>
                <label className="block text-gray-300 text-sm mb-1">Mã PIN</label>
                <input
                  type="password"
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                  placeholder="Nhập PIN nhân viên"
                  className="w-full px-4 py-3 rounded-lg bg-gray-700 text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-orange-500"
                  autoFocus
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 rounded-lg bg-orange-600 hover:bg-orange-700 text-white font-semibold disabled:opacity-50 transition-colors"
              >
                {loading ? "Đang đăng nhập..." : "Đăng nhập"}
              </button>
            </>
          )}

          {error && (
            <p className="text-red-400 text-sm text-center">{error}</p>
          )}
        </form>
      </div>
    </div>
  );
}
