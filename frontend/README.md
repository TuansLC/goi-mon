# QOrder Frontend — Customer Menu

Ứng dụng React cho khách hàng: quét QR → xem menu → gọi món.

## Yêu cầu

- Node.js 18+
- npm

## Cài đặt

```bash
cd frontend
npm install
```

## Chạy dev

```bash
npm run dev
```

Mặc định chạy tại `http://localhost:5173`. Truy cập theo path `/{slug}/t/{qr_token}`.

## Biến môi trường

| Biến | Mô tả | Mặc định |
|------|--------|----------|
| `VITE_API_BASE_URL` | URL backend API | `http://localhost:8000` |

## Build production

```bash
npm run build
```

Output nằm trong `dist/`.

## Cấu trúc

```
src/
├── api.ts                 # API client (fetch)
├── types.ts               # TypeScript types (matching backend schemas)
├── App.tsx                # Router setup
├── main.tsx               # Entry point
├── index.css              # TailwindCSS imports
├── components/
│   ├── Cart.tsx           # Cart modal
│   └── MenuCategorySection.tsx  # Menu grouped by category
├── hooks/
│   └── useCart.ts         # Cart state management
└── pages/
    └── MenuPage.tsx       # Main page: menu + cart + order
```
