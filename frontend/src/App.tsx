import { Composer, Thread } from "./components/Chat";
import { Header } from "./components/Header";
import { ApprovalModal, CaptionBar, ConsentModal, Toast } from "./components/Modals";
import { Intro, Outro } from "./components/TitleCards";
import { WhyPanel } from "./components/WhyPanel";
import { EvidenceCenter } from "./evidence/EvidenceCenter";
import { isDemo, useDemoCaption, usePath } from "./lib/demo";
import { StoreProvider } from "./lib/store";

function MainPage() {
  return (
    <div className="flex h-full flex-col">
      <Header />
      <div className="mx-auto grid min-h-0 w-full max-w-[1720px] flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_440px]">
        <main className="flex min-h-0 flex-col">
          <div className="flex-1 overflow-y-auto px-6 py-6">
            <Thread />
          </div>
          <Composer />
        </main>
        <div className="hidden min-h-0 lg:block">
          <WhyPanel />
        </div>
      </div>
      <ApprovalModal />
      <ConsentModal />
    </div>
  );
}

function EvidencePage() {
  return (
    <div className="flex h-full flex-col">
      <Header evidence />
      <div className="flex-1 overflow-y-auto">
        <EvidenceCenter />
      </div>
    </div>
  );
}

export default function App() {
  const path = usePath();
  const demo = isDemo();
  const caption = useDemoCaption();
  let page = <MainPage />;
  if (path.startsWith("/evidence")) page = <EvidencePage />;
  else if (path.startsWith("/intro")) page = <Intro />;
  else if (path.startsWith("/outro")) page = <Outro />;
  return (
    <StoreProvider>
      {page}
      <Toast />
      {demo && <CaptionBar text={caption} />}
    </StoreProvider>
  );
}
