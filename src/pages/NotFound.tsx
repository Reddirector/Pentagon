import { motion } from "framer-motion";
import Polyhedron from "@/components/Polyhedron";

export default function NotFound() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="flex min-h-screen flex-col bg-background"
    >
      {/* Main Content */}
      <div className="flex flex-1 flex-col items-center justify-center">
        <div className="relative mx-auto max-w-5xl px-4">
          <div className="flex min-h-[300px] items-center justify-center">
            <div className="ptg-stars w-full max-w-sm rounded-2xl bg-card/60 p-8 ptg-border text-center shadow-2xl shadow-black/40 backdrop-blur-xl">
              <div className="mb-4 flex justify-center">
                <Polyhedron size={72} orbits />
              </div>
              <h1 className="text-5xl font-semibold tracking-tight text-foreground">
                404
              </h1>
              <p className="mt-2 text-xs font-medium uppercase tracking-[0.3em] text-muted-foreground">
                Page Not Found
              </p>
              <a
                href="/"
                className="mt-6 inline-block rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                Back home
              </a>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
