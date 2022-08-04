import numpy as np
import numpy.linalg as la
import re
import subprocess
import shutil

# Parameters
postol = 1e-5 # Tolerence for c position in poscar

def prepare_incar(ibrion):

    if not os.path.is_file("INCAR.save"):
        shutil.copyfile("INCAR", "INCAR.save")

    # Read Vasp input files
    with open("INCAR", "r") as f:
        old_incar = f.read()

    if re.search("IBRION\s*=\s*[\-0-9]+", old_incar):
        new_incar =  re.sub("(IBRION\s*=\s*)[\-0-9]+", "\g<1>%d"%ibrion, old_incar)
    else:
        new_incar = old_incar + ("\n" if old_incar[-1] != "\n" else "\n") + "IBRION = %d\n"%ibrion

    new_incar =  re.sub("NSW\s*=\s*[\-0-9]+", "", new_incar)

    new_incar =  re.sub("(ISTART\s*=\s*)[\-0-9]+", "\g<1>1", new_incar)

    new_incar =  re.sub("(ICHARG\s*=\s*)[\-0-9]+", "\g<1>0", new_incar)

    with open("INCAR", "w") as f:
        f.write(new_incar)
    
def read_poscar(file="POSCAR"):
    with open(file, "r") as f:
        old_poscar = f.readlines()

    scale = float(old_poscar[1].strip())

    cell = np.empty((3,3))
    for i in range(3):
        cell[:,i] = [float(a) for a in old_poscar[i+2].split()]

    cell = cell*scale

    if re.search("^\s*(?:[0-9]+\s*)+$", old_poscar[5]):
        # Use potcar atoms
        with open("POTCAR", "r") as f:
            potcar = f.read()
        elements = np.array(re.findall("TITEL\s*=\s*\w+\s*(\w+)", potcar))
        nelem = np.cumsum([int(a) for a in old_poscar[5].split()])
        last = 5
    else:
        elements = np.array(old_poscar[5].split())
        nelem = np.cumsum([int(a) for a in old_poscar[6].split()])
        last = 6

    selective = old_poscar[last+1].strip()[0].lower()=="s"

    last += (1 if selective else 0)

    cartesian = old_poscar[last + 1].strip()[0].lower() in ["c","k"]

    atoms = []
    for i, line in enumerate(old_poscar[last+2:]):
        if re.search("^\s*(?:[\-0-9\.]+(?:e[\-\+]?[0-9]{1,3})?\s*){3}", line):
            content = line.split()
        else:
            break
        pos = np.array([float(a) for a in content[:3]])
        
        if cartesian:
            pos = la.inv(cell).dot(pos*scale)

        elem = elements[i<=nelem-1][0]
        
        if selective:
            sel = np.array(content[3:])
        else:
            sel = None
            
        atoms.append([elem,pos,sel])

    return cell, atoms

def write_poscar(cell,atoms):

    poscar = "This poscar was generated by VaspGibbs\n1.0\n"

    for i in range(3):
        poscar += "%f %f %f\n"%(*list(cell[:,i]),)

    elements = {}
    for elem, _, _ in atoms:
        if elem in elements:
            elements[elem] += 1
        else:
            elements[elem] = 1

    poscar += " ".join(list(elements.keys())) + "\n"

    poscar += " ".join([str(a) for a in list(elements.values())]) + "\n"

    poscar += "Selective dynamics\nDirect\n"

    for _,pos,sel in atoms:
        poscar += " ".join([str(a) for a in pos]) + " "
        poscar += " ".join(sel) + "\n"

    with open("POSCAR", "w") as f:
        f.write(poscar)

def prepare_poscar(cell, atoms, list_atoms, top, tol=postol):

    z = []
    for i,a in enumerate(atoms):
        elem, pos, sel = a
        if (elem in list_atoms) or (str(i) in list_atoms):
            sel = np.array(["T","T","T"])
        else:
            sel = np.array(["F","F","F"])
        a[2] = sel
        z.append((pos[2]+tol)%1)

    if (list_atoms == []) and (top == 0):
        top = len(atoms)

    idx  = np.argsort(z)
    for i in range(top):
        atoms[idx[-(i+1)]][2] = np.array(["T","T","T"])
    
    write_poscar(cell,atoms)

    return cell,atoms

def run_vasp(command, ncores, vasp):
    if ncores == 1:
        subprocess.run([vasp], check=True)
    else:
        subprocess.run([command, "-n", str(ncores), vasp], check=True)

def read_outcar():
    try:
        with open("OUTCAR", "r") as f:
            outcar = f.read()
    except FileNotFoundError:
        return False, None, None, None

    success = re.search("General timing and accounting informations for this job", outcar) is not None

    if not success:
        return False, None, None, None

    ibrion =  int(re.findall("IBRION\s*=\s*([\-0-9]+)", outcar)[-1])

    freq = []
    if re.search("Eigenvectors and eigenvalues of the dynamical matrix", outcar):
        for match in re.finditer("[0-9]+\sf(\/i)*\s*=\s*([0-9.]+)", outcar):
            if match.group(1) is None:
                freq.append(float(match.group(2)))
            else:
                freq.append(float(match.group(2))*(0+1j))
        freq = np.array(freq)
    else:
        freq = None

    E_dft = float(re.findall("energy  without.*sigma\->0\)\s*=\s*([0-9\-\.]+)\s*", outcar)[0])

    return success, ibrion, freq, E_dft

def reposition():
    cell_old, atoms_old = read_poscar("POSCAR.save")
    cell, atoms = read_poscar()

    for i, a in enumerate(atoms):

        distmin = None
        for j in [0,-1]:
            for k in [0,-1]:
                for l in [0,-1]:
                    dist = la.norm(cell.dot(a[1] + [j,k,l]) - cell_old.dot(atoms_old[i][1]))
                    if distmin is None or dist < distmin:
                        distmin = dist
                        shift = [j,k,l]
        if a[2] is None:
            atoms[i] = (a[0], a[1] + shift, ["T","T","T"])
        else:
            atoms[i] = (a[0], a[1] + shift, a[2])

    write_poscar(cell, atoms)
