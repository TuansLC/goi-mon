import { Routes, Route, Navigate } from "react-router-dom";
import MenuPage from "./pages/MenuPage";
import { KitchenLayout, KitchenLoginPage, KitchenBoard } from "./kitchen";
import {
  AdminLayout,
  MenuManagementPage,
  TableManagementPage,
  SettingsPage,
  SessionsPage,
  ReportsPage,
} from "./admin";

function App() {
  return (
    <Routes>
      {/* Customer routes */}
      <Route path="/:slug/t/:qrToken" element={<MenuPage />} />

      {/* Kitchen routes */}
      <Route element={<KitchenLayout />}>
        <Route path="/kitchen" element={<KitchenLoginPage />} />
        <Route path="/:slug/kitchen" element={<KitchenLoginPage />} />
        <Route path="/:slug/kitchen/board" element={<KitchenBoard />} />
      </Route>

      {/* Admin routes */}
      <Route path="/admin" element={<AdminLayout />}>
        <Route index element={<Navigate to="/admin/menu" replace />} />
        <Route path="menu" element={<MenuManagementPage />} />
        <Route path="tables" element={<TableManagementPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="sessions" element={<SessionsPage />} />
        <Route path="reports" element={<ReportsPage />} />
      </Route>
      <Route path="/:slug/admin" element={<AdminLayout />}>
        <Route index element={<Navigate to="menu" replace />} />
        <Route path="menu" element={<MenuManagementPage />} />
        <Route path="tables" element={<TableManagementPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="sessions" element={<SessionsPage />} />
        <Route path="reports" element={<ReportsPage />} />
      </Route>
    </Routes>
  );
}

export default App;
