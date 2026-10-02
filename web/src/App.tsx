import { lazy, Suspense, type ComponentType } from "react";
import { createBrowserRouter, RouterProvider, type RouteObject } from "react-router-dom";
import { SessionProvider } from "./state";
import { Shell } from "./components/Shell";
import { Loading } from "./components/Bits";
import { Home } from "./pages/Home";
import { Search } from "./pages/Search";
import { Ask } from "./pages/Ask";
import { Basket, KnowledgeMap, SharedList, Stories, Story, Timeline } from "./pages/Explore";
import { Signage } from "./pages/Signage";
import { KioskMode } from "./pages/Kiosk";
import { NotFound } from "./pages/NotFound";

const staff = () => import("./staff/Staff");
function named<M>(load: () => Promise<M>, name: keyof M): ComponentType {
  const C = lazy(async () => ({ default: (await load())[name] as ComponentType }));
  return function LazyRoute() {
    return (
      <Suspense fallback={<Loading />}>
        <C />
      </Suspense>
    );
  };
}
const Item = named(() => import("./pages/Item"), "Item");
const Constitution = named(() => import("./pages/Constitution"), "Constitution");
const ConstitutionArticlePage = named(() => import("./pages/Constitution"), "ConstitutionArticlePage");
const StaffRoot = named(staff, "StaffRoot");
const StaffLogin = named(staff, "StaffLogin");
const StaffLayout = named(staff, "StaffLayout");
const StaffDashboard = named(staff, "StaffDashboard");
const StaffIntake = named(staff, "StaffIntake");
const StaffReview = named(staff, "StaffReview");
const StaffItems = named(staff, "StaffItems");
const StaffItem = named(staff, "StaffItem");
const StaffPage = named(staff, "StaffPage");
const StaffBatch = named(staff, "StaffBatch");
const StaffRights = named(staff, "StaffRights");
const StaffJobs = named(staff, "StaffJobs");
const StaffCuration = named(staff, "StaffCuration");
const StaffAudit = named(staff, "StaffAudit");

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Home /> },
      { path: "search", element: <Search /> },
      { path: "ask", element: <Ask /> },
      { path: "item/:id", element: <Item /> },
      { path: "timeline", element: <Timeline /> },
      { path: "stories", element: <Stories /> },
      { path: "stories/:slug", element: <Story /> },
      { path: "map", element: <KnowledgeMap /> },
      { path: "constitution", element: <Constitution /> },
      { path: "constitution/:number", element: <ConstitutionArticlePage /> },
      { path: "list", element: <Basket /> },
      { path: "*", element: <NotFound /> },
    ],
  },
  { path: "/c/:token", element: <SharedList /> },
  { path: "/display", element: <Signage /> },
  { path: "/kiosk", element: <KioskMode /> },
  {
    path: "/staff",
    element: <StaffRoot />,
    children: [
      { path: "login", element: <StaffLogin /> },
      {
        element: <StaffLayout />,
        children: [
          { index: true, element: <StaffDashboard /> },
          { path: "intake", element: <StaffIntake /> },
          { path: "review", element: <StaffReview /> },
          { path: "items", element: <StaffItems /> },
          { path: "items/:id", element: <StaffItem /> },
          { path: "pages/:id", element: <StaffPage /> },
          { path: "batches/:id", element: <StaffBatch /> },
          { path: "rights", element: <StaffRights /> },
          { path: "curation", element: <StaffCuration /> },
          { path: "jobs", element: <StaffJobs /> },
          { path: "audit", element: <StaffAudit /> },
        ],
      },
    ],
  },
];

let router: ReturnType<typeof createBrowserRouter> | null = null;

export function App() {
  router ??= createBrowserRouter(routes);
  return (
    <SessionProvider>
      <RouterProvider router={router} />
    </SessionProvider>
  );
}
