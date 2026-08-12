/**
 * Admin Layout — sidebar navigation + auth guard.
 */

import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { AdminAuthProvider, useAdminAuth } from "./AdminAuthContext";

function AdminSidebar() {
  const { logout } = useAdminAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/admin", { replace: true });
  };

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `block px-4 py-2 rounded-lg transition-colors ${
      isActive
        ? "bg-blue-600 text-white"
        : "text-gray-700 hover:bg-gray-200"
    }`;

  return (
    <aside className="w-64 bg-white border-r border-gray-200 min-h-screen p-4 flex flex-col">
      <h2 className="text-xl font-bold text-gray-800 mb-6 px-4">
        🔧 Admin
      </h2>

      <nav className="flex-1 space-y-1">
        <NavLink to="/admin/menu" className={linkClass}>
          📋 Menu & Nhóm
        </NavLink>
        <NavLink to="/admin/tables" className={linkClass}>
          🪑 Quản lý bàn
        </NavLink>
        <NavLink to="/admin/settings" className={linkClass}>
          ⚙️ Cài đặt
        </NavLink>
        <NavLink to="/admin/sessions" className={linkClass}>
          📦 Phiên abandoned
        </NavLink>
        <NavLink to="/admin/reports" className={linkClass}>
          📊 Báo cáo
        </NavLink>
      </nav>

      <button
        onClick={handleLogout}
        className="mt-4 px-4 py-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors text-left"
      >
        🚪 Đăng xuất
      </button>
    </aside>
  );
}

function AdminGuard() {
  const { isAuthenticated } = useAdminAuth();

  if (!isAuthenticated) {
    return <AdminLoginPage />;
  }

  return (
    <div className="flex min-h-screen bg-gray-50">
      <AdminSidebar />
      <main className="flex-1 p-6 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

// Import here to avoid circular deps
import AdminLoginPage from "./AdminLoginPage";

export default function AdminLayout() {
  return (
    <AdminAuthProvider>
      <AdminGuard />
    </AdminAuthProvider>
  );
}
