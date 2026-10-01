import { motion } from "framer-motion";

export default function NotFound() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="min-h-screen flex flex-col"
    >

      
      {/* Main Content */}
      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="max-w-5xl mx-auto relative px-4">
          <div className="flex items-center justify-center min-h-[200px]">
            <div className="nb-grid-bg bg-background w-full max-w-sm p-8 text-center nb-border nb-offset">
              <h1 className="text-5xl font-black uppercase text-foreground">
                404
              </h1>
              <p className="mt-2 text-sm font-bold uppercase tracking-widest text-muted-foreground">
                Page Not Found
              </p>
              <a
                href="/"
                className="mt-6 inline-block bg-primary px-4 py-2 text-sm font-black uppercase nb-border nb-press"
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
