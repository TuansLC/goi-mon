/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    // The customer (QR) theme lives in `src/index.css` as CSS custom properties
    // plus `qo-*` component classes — see the comment block there.
    extend: {},
  },
  plugins: [],
};
